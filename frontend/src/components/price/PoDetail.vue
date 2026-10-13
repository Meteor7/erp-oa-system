<script setup>
// 一张 PO 的详情：合同办理步骤、合同信息、物料明细、到货 / 验收 / 付款进度（只读）、付款计划、合同审批轨迹。
// 到货与验收由生产主管在"采购付款"里登记，这里只看进度；PO 生成后系统不提供取消。
import { computed, ref, watch } from 'vue';
import {
  contractDraftFor, contractFields, contractMode, contractPayload, contractStepper, deliveryPayload,
  amountText, inspectionTone, isPoDraft, maskAccount, missingDelivery, paymentLink, paymentPoLink, pillClass, planStatus, poCloseBlockers,
  poHeaderDiffers, poLineTotal, poMainAction, poProgress, poSources, poTone, poTrail, quantity, shortDate, splitList,
} from '../../lib/priceView.js';

const props = defineProps({
  po: { type: Object, required: true },
  busy: { type: Boolean, default: false },
});
const emit = defineEmits(['back', 'open-approval', 'save-delivery', 'confirm', 'generate', 'review', 'seal', 'close']);

const deliveryDraft = ref({});
const contractDraft = ref({});
const confirming = ref('');
const localError = ref('');

function resetDrafts() {
  const draft = {};
  (props.po.lines || []).forEach((line) => { draft[line.name] = line.contract_delivery_date || ''; });
  deliveryDraft.value = draft;
  contractDraft.value = contractDraftFor(props.po);
  confirming.value = '';
  localError.value = '';
}
watch([() => props.po.name, () => props.po.modified], resetDrafts, { immediate: true });

const mode = computed(() => contractMode(props.po));
const manage = computed(() => Boolean(props.po.can_manage_purchase));
const draftEditable = computed(() => mode.value === 'draft' && manage.value);
const fillEditable = computed(() => mode.value === 'fill' && manage.value);
const main = computed(() => poMainAction(props.po));
const stepper = computed(() => contractStepper(props.po));
const progress = computed(() => poProgress(props.po));
const blockers = computed(() => poCloseBlockers(props.po));
const fields = computed(() => contractFields(props.po));
const trail = computed(() => poTrail(props.po));
const sources = computed(() => poSources(props.po));
const approvalNames = computed(() => splitList(props.po.source_price_approvals));
const showContract = computed(() => mode.value !== 'draft' && mode.value !== 'cancelled');
const executing = computed(() => mode.value === 'effective');
const closed = computed(() => props.po.status === '已关闭');
const plan = computed(() => props.po.payment_plan || []);
const subline = computed(() => [
  props.po.supplier, props.po.payment_method,
  approvalNames.value.length ? `来源 ${approvalNames.value.join('、')}` : '',
  sources.value.requests.join('、'), props.po.contract_entity,
].filter(Boolean).join(' · '));
const confirmText = computed(() => ({
  seal: '确认电子用印？用印后合同生效，符合条件的付款期次可以提交付款审批。',
  close: '确认关闭 PO？关闭后不能再登记到货、验收和付款。',
}[confirming.value] || ''));

function fieldValue(field) {
  if (field.secret) return maskAccount(field.value) || '—';
  if (field.date) return shortDate(field.value);
  return field.value || '—';
}
function runMain() {
  localError.value = '';
  const key = main.value.key;
  if (key === 'confirm') {
    const missing = missingDelivery(props.po, deliveryDraft.value);
    if (missing) { localError.value = `还有 ${missing} 项物料没有填合同交期，每项都要确认才能确认 PO。`; return; }
    emit('confirm', deliveryPayload(props.po, deliveryDraft.value));
  } else if (key === 'generate') {
    if (!String(contractDraft.value.supplier_legal_name || '').trim()) { localError.value = '请填写供应商全称。'; return; }
    emit('generate', contractPayload(props.po, contractDraft.value));
  } else if (key === 'review') emit('review');
  else if (key === 'seal') confirming.value = 'seal';
}
function saveDelivery() {
  localError.value = '';
  emit('save-delivery', deliveryPayload(props.po, deliveryDraft.value));
}
function runConfirmed() {
  const key = confirming.value;
  confirming.value = '';
  if (key === 'seal') emit('seal');
  else if (key === 'close') emit('close');
}
// PMC、生产主管看不到金额（服务端去掉了，amounts_hidden）：显示“—”
const cash = (value) => amountText(value, props.po.amounts_hidden);
</script>

<template>
  <div class="pa-po-detail">
    <div class="crumb"><button type="button" class="link" @click="emit('back')">PO 与合同</button> › {{ po.name }}</div>

    <section class="panel pa-head">
      <div class="detail-head">
        <div class="grow-col">
          <div class="title-line"><h3 class="num">{{ po.name }}</h3><span :class="pillClass(poTone(po.status))">{{ po.status }}</span></div>
          <div class="muted">{{ subline }}</div>
        </div>
        <div class="amount-block" title="物料行金额合计">
          <span class="muted">PO 总额（行合计）</span><b>{{ cash(poLineTotal(po)) }}</b>
          <span v-if="!po.amounts_hidden && poHeaderDiffers(po)" class="muted">表头 {{ cash(po.total_amount) }}</span>
        </div>
        <div class="head-buttons">
          <button v-if="draftEditable" type="button" class="btn" :disabled="busy" @click="saveDelivery">保存合同交期</button>
          <button v-if="main.key" type="button" class="btn pri lg" :disabled="busy" @click="runMain">{{ main.text }}</button>
          <span v-if="main.wait" class="pill p-gray">{{ main.wait }}</span>
        </div>
      </div>

      <div v-if="confirming" class="pa-confirm" role="alertdialog" aria-label="确认操作">
        <span>{{ confirmText }}</span>
        <button type="button" class="btn sm pri" :disabled="busy" @click="runConfirmed">确认</button>
        <button type="button" class="btn sm" @click="confirming = ''">返回</button>
      </div>
      <div v-if="localError" class="err" role="alert">{{ localError }}</div>

      <ol class="pa-stepper" aria-label="合同办理进度">
        <li v-for="step in stepper" :key="step.label" :class="{ done: step.done, now: step.now }">
          <div class="pa-step-line"><i>{{ step.mark }}</i><span></span></div>
          <b>{{ step.label }}</b>
          <span class="muted">{{ step.sub }}</span>
        </li>
      </ol>
    </section>

    <div class="detail-grid">
      <div class="pa-po-main">
        <section v-if="showContract" class="panel pa-contract">
          <div class="pt">
            <span>合同信息</span>
            <span class="muted">合同模板：{{ po.contract_template || '标准采购合同' }}<template v-if="Number(po.contract_version) > 0"> · 版本 v{{ po.contract_version }}</template> · 用印人固定为副总经理</span>
          </div>
          <div class="pa-contract-grid">
            <div v-for="field in fields" :key="field.key" :class="['pa-cfield', { wide: field.wide }]">
              <label :for="`pa-c-${field.key}`" class="muted">{{ field.label }}</label>
              <template v-if="fillEditable">
                <input v-if="field.date" :id="`pa-c-${field.key}`" v-model="contractDraft[field.key]" class="cell" type="date" />
                <input v-else :id="`pa-c-${field.key}`" v-model="contractDraft[field.key]" class="cell" :placeholder="field.key === 'supplier_legal_name' ? '请核对供应商全称' : '请填写'" autocomplete="off" />
              </template>
              <span v-else class="pa-cvalue">{{ fieldValue(field) }}</span>
            </div>
          </div>
          <p v-if="fillEditable" class="muted foot">补充后点右上"生成合同草稿"；没填的字段不会覆盖已有内容。</p>
          <div v-if="mode === 'review' && po.contract_draft_content" class="pa-draft-box">
            <div class="muted">合同草稿（复核时核对）</div>
            <pre>{{ po.contract_draft_content }}</pre>
          </div>
        </section>

        <section class="panel pa-lines">
          <div class="pt"><span>物料明细 <span class="muted">{{ (po.lines || []).length }} 项 · 来自 {{ sources.requests.join('、') || '—' }}</span></span></div>
          <div class="tbl">
            <table>
              <thead>
                <tr><th>流水号 / 来源</th><th>物料 / 型号</th><th class="r">数量</th><th class="r">单价</th><th class="r">金额</th><th>OA 预计交期</th><th>合同交期</th><th class="r">到货 / 验收</th></tr>
              </thead>
              <tbody>
                <tr v-for="line in po.lines" :key="line.name">
                  <td>
                    <div class="num">{{ line.material_serial }}</div>
                    <div class="muted">{{ line.source_request || '—' }}<template v-if="line.project"> · {{ line.project }}</template></div>
                    <div v-if="line.source_pr" class="muted">{{ line.source_pr }}</div>
                  </td>
                  <td><b>{{ line.item_name }}</b><div class="muted">{{ line.specification || '—' }}</div></td>
                  <td class="r num">{{ quantity(line.quantity) }} {{ line.unit }}</td>
                  <td class="r num">{{ cash(line.unit_price) }}</td>
                  <td class="r num strong">{{ cash(line.amount) }}</td>
                  <td class="num">{{ shortDate(line.expected_delivery_date) }}</td>
                  <td>
                    <input v-if="draftEditable" v-model="deliveryDraft[line.name]" class="cell" type="date" :aria-label="`${line.item_name} 合同交期`" />
                    <span v-else class="num">{{ shortDate(line.contract_delivery_date) }}</span>
                  </td>
                  <td class="r">
                    <template v-if="executing || closed">
                      <div class="num">{{ quantity(line.received_quantity) }} / {{ quantity(line.quantity) }}</div>
                      <span :class="pillClass(inspectionTone(line.inspection_status))">{{ line.inspection_status || '未验收' }}</span>
                    </template>
                    <span v-else class="muted">—</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <p class="muted foot">一张 PO 的物料可能来自好几张 OA、好几个项目，每行各写各的来源。</p>
        </section>

        <section v-if="executing || closed" class="panel pa-exec">
          <div class="pt"><span>到货与验收</span><router-link :to="paymentPoLink(po)" class="link">去登记 / 看记录 →</router-link></div>
          <div class="pa-exec-stats">
            <div><span class="muted">到货</span><b>{{ progress.received }} / {{ progress.lineCount }} 项到齐</b></div>
            <div><span class="muted">验收通过</span><b>{{ progress.passed }} / {{ progress.lineCount }} 项</b></div>
            <div><span class="muted">已付</span><b>{{ cash(progress.paid) }} / {{ cash(progress.total) }}</b></div>
          </div>
          <div class="pa-close-row">
            <template v-if="closed"><span class="pill p-jade">PO 已关闭</span></template>
            <template v-else-if="manage">
              <button type="button" class="btn" :disabled="busy || blockers.length > 0" @click="confirming = 'close'">校验并关闭 PO</button>
              <span v-if="blockers.length" class="warn pa-missing">还差：{{ blockers.join('；') }}（满足后由采购关闭）</span>
              <span v-else class="ok">已满足全部条件，可以关闭。</span>
            </template>
            <span v-else-if="blockers.length" class="warn pa-missing">还差：{{ blockers.join('；') }}（满足后由采购关闭）</span>
          </div>
          <p class="muted foot">到货和验收都由生产主管登记，按整张 PO 逐项登记（含换货、退货），在"采购付款"里操作，这里只看进度。</p>
        </section>
      </div>

      <aside class="pa-po-side">
        <section class="panel pa-plan">
          <div class="pt"><span>付款计划</span><span class="muted">付款方式：{{ po.payment_method || '—' }}</span></div>
          <div v-for="row in plan" :key="row.name || row.installment_no" class="pa-plan-item">
            <div class="split">
              <b>{{ row.installment_name || `第${row.installment_no}期` }} · {{ row.payment_stage }} {{ Number(row.percentage || 0) }}%</b>
              <span :class="pillClass(planStatus(row).tone)">{{ planStatus(row).text }}</span>
            </div>
            <span class="muted">触发条件：{{ row.trigger_condition || '—' }}</span>
            <span class="muted">计划 {{ shortDate(row.planned_date) }} · 发票 {{ row.invoice_requirement || '—' }}</span>
            <div class="split"><b class="num">{{ cash(row.amount) }}</b><router-link v-if="row.payment_request" :to="paymentLink(row)" class="link">{{ row.payment_request }} →</router-link></div>
          </div>
          <div v-if="!plan.length" class="empty">暂无付款计划</div>
          <router-link :to="paymentPoLink(po)" class="pa-pay-link">付款条件、提交付款审批 → 采购付款（{{ po.name }}）</router-link>
          <p class="muted foot">付款条件与执行在采购付款工作台处理：到货资料、验收资料、付款期次条件、付款审批和实际付款都在那里。</p>
        </section>

        <section v-if="approvalNames.length" class="panel pa-sources">
          <div class="pt"><span>来源价格审批单</span></div>
          <div class="pa-source-links">
            <button v-for="name in approvalNames" :key="name" type="button" class="link strong" @click="emit('open-approval', name)">{{ name }} →</button>
          </div>
        </section>

        <section class="panel pa-trail">
          <div class="pt"><span>合同审批轨迹</span></div>
          <div v-for="item in trail" :key="item.key" class="pa-trail-row"><span class="muted">{{ item.time }}</span><span>{{ item.text }}</span></div>
          <div v-if="!trail.length" class="empty">暂无记录</div>
          <p class="muted foot">同一个采购人员可以生成、复核、确认合同；用印只能是副总经理。PO 生成后系统不提供取消，生成前请在价格审批里核对。</p>
        </section>
      </aside>
    </div>
  </div>
</template>
