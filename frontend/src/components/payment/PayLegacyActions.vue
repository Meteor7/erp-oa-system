<script setup>
// 没有来源 PO 的旧采购付款（旧数据：来源申请 + 付款计划行）：保留旧的付款后流程——
// 登记到货 / 登记验收 / 预付款跟进 / 确认供应商退款（财务）/ 预付款核销 / 关闭采购。
// 来源 PO 的付款不会显示这个区块（服务端会拒绝这些操作）。
import { computed, ref } from 'vue';
import { createResource } from 'frappe-ui';
import { legacyActions } from '../../lib/paymentView.js';
import { OA_API, errorText } from './paymentApi.js';

const props = defineProps({
  request: { type: Object, required: true },
  documents: { type: Array, default: () => [] },
  canManageExpense: { type: Boolean, default: false },
});
const emit = defineEmits(['changed']);

const arrivalRecorder = createResource({ url: OA_API + 'record_arrival' });
const inspectionRecorder = createResource({ url: OA_API + 'record_inspection' });
const followupRecorder = createResource({ url: OA_API + 'record_prepayment_followup' });
const refundCompleter = createResource({ url: OA_API + 'complete_supplier_refund' });
const writeoffRecorder = createResource({ url: OA_API + 'writeoff_prepayment' });
const closeRecorder = createResource({ url: OA_API + 'close_procurement' });

const actions = computed(() => legacyActions(props.request, props.documents, { canManageExpense: props.canManageExpense }));
const arrivalQuantity = ref(0);
const arrivalDate = ref('');
const inspectionOutcome = ref('通过');
const inspectionDirection = ref('退货');
const inspectionReason = ref('');
const followupStatus = ref('催办中');
const followupReason = ref('');
const note = ref('');
const busy = ref(false);
const ok = ref('');
const error = ref('');

async function run(resource, params, okText, fallback) {
  if (busy.value) return;
  busy.value = true;
  ok.value = '';
  error.value = '';
  try {
    await resource.submit({ name: props.request.name, ...params });
    ok.value = okText;
    emit('changed');
  } catch (err) { error.value = errorText(err, fallback); } finally { busy.value = false; }
}
const recordArrival = () => run(arrivalRecorder, { quantity: arrivalQuantity.value, arrival_date: arrivalDate.value }, '到货已登记', '到货登记失败');
const recordInspection = () => run(inspectionRecorder, { outcome: inspectionOutcome.value, reason: inspectionReason.value, direction: inspectionDirection.value }, '验收已登记', '验收登记失败');
const recordFollowup = () => run(followupRecorder, { status: followupStatus.value, reason: followupReason.value }, '异常跟进已登记', '异常跟进登记失败');
const completeRefund = () => run(refundCompleter, { reason: followupReason.value }, '供应商退款已确认', '供应商退款确认失败');
const writeoff = () => run(writeoffRecorder, { reason: note.value }, '预付款已核销', '预付款核销失败');
const closeOrder = () => run(closeRecorder, { reason: note.value }, '采购已关闭', '采购关闭失败');
</script>

<template>
  <section v-if="actions.show" class="panel pay-legacy">
    <div class="pt"><span>付款后跟进 <span class="muted">旧数据（没有来源 PO）的到货 / 验收 / 预付款处理</span></span></div>
    <p class="muted">到货 {{ request.received_quantity }}/{{ request.ordered_quantity }} · {{ request.arrival_status || '-' }} · {{ request.inspection_status || '-' }}</p>
    <div v-if="ok" class="banner ok" role="status">{{ ok }}</div>
    <div v-if="error" class="banner err" role="alert">{{ error }}</div>

    <div v-if="actions.arrival" class="pay-legacy-row">
      <input v-model.number="arrivalQuantity" type="number" class="cell" placeholder="到货数量" aria-label="到货数量" />
      <input v-model="arrivalDate" type="date" class="cell" aria-label="到货日期" />
      <button type="button" class="btn dark" :disabled="busy" @click="recordArrival">登记到货</button>
    </div>
    <div v-if="actions.inspection" class="pay-legacy-row">
      <select v-model="inspectionOutcome" class="cell" aria-label="验收结果"><option>通过</option><option>不合格</option></select>
      <select v-if="inspectionOutcome === '不合格'" v-model="inspectionDirection" class="cell" aria-label="处理方向"><option>退货</option><option>换货</option></select>
      <input v-model="inspectionReason" type="text" class="cell" placeholder="验收说明/不合格原因" aria-label="验收说明" />
      <button type="button" class="btn dark" :disabled="busy" @click="recordInspection">登记验收</button>
    </div>
    <div v-if="actions.followup" class="pay-legacy-row">
      <select v-model="followupStatus" class="cell" aria-label="跟进状态"><option>催办中</option><option>供应商退款中</option><option>退货中</option><option>换货中</option></select>
      <input v-model="followupReason" type="text" class="cell" placeholder="异常跟进说明" aria-label="异常跟进说明" />
      <button type="button" class="btn" :disabled="busy" @click="recordFollowup">记录跟进</button>
    </div>
    <div v-if="actions.writeoff || actions.close" class="pay-legacy-row">
      <input v-model="note" type="text" class="cell" placeholder="核销 / 关闭说明（可选）" aria-label="核销或关闭说明" />
    </div>
    <div class="head-actions">
      <button v-if="actions.refund" type="button" class="btn pri" :disabled="busy" @click="completeRefund">确认供应商退款</button>
      <button v-if="actions.writeoff" type="button" class="btn pri" :disabled="busy" @click="writeoff">预付款核销</button>
      <button v-if="actions.close" type="button" class="btn dark" :disabled="busy" @click="closeOrder">关闭采购</button>
    </div>
  </section>
</template>
