<script setup>
// 右侧抽屉：编辑（或新增）一家供应商对整张价格审批单的报价 + 商务条件 + 付款计划。只有采购、草稿状态下才会打开。
import { computed, nextTick, ref, watch } from 'vue';
import {
  INVOICE_REQUIREMENTS, PAYMENT_STAGES, TRIGGER_SUGGESTIONS, amountFromPercentage, draftLineTotal, draftTotal,
  emptySupplierDraft, fillPlanAmounts, money, newPlanRow, planTotals, quantity, supplierDraftFromGroup,
  supplierPayload, validateSupplierDraft,
} from '../../lib/priceView.js';

const props = defineProps({
  open: { type: Boolean, default: false },
  approval: { type: Object, default: null },
  supplier: { type: String, default: '' },
  busy: { type: Boolean, default: false },
  error: { type: String, default: '' },
});
const emit = defineEmits(['save', 'delete', 'close']);

const draft = ref(null);
const tried = ref(false);
const askDelete = ref(false);
const panel = ref(null);

const lines = computed(() => props.approval?.lines || []);
const total = computed(() => (draft.value ? draftTotal(props.approval, draft.value) : 0));
const totals = computed(() => (draft.value ? planTotals(draft.value) : { percentage: 0, amount: 0 }));
const errors = computed(() => (draft.value ? validateSupplierDraft(props.approval, draft.value) : []));
const isExisting = computed(() => Boolean(draft.value?.original_supplier));
const planMatches = computed(() => Math.abs(totals.value.percentage - 100) <= 0.0001 && Math.abs(totals.value.amount - total.value) <= 0.01);

watch([() => props.open, () => props.supplier, () => props.approval?.name], () => {
  tried.value = false;
  askDelete.value = false;
  if (!props.open || !props.approval) { draft.value = null; return; }
  const group = props.supplier ? (props.approval.supplier_comparisons || []).find((item) => item.supplier === props.supplier) : null;
  draft.value = group ? supplierDraftFromGroup(props.approval, group) : emptySupplierDraft(props.approval);
  nextTick(() => panel.value?.querySelector('input')?.focus());
}, { immediate: true });

function setPercentage(row, value) {
  row.percentage = value === '' ? '' : Number(value);
  if (total.value > 0) row.amount = amountFromPercentage(total.value, row.percentage);
}
function addRow() {
  draft.value.payment_plan.push(newPlanRow(draft.value.payment_plan.length + 1));
}
function removeRow(index) {
  if (draft.value.payment_plan.length > 1) draft.value.payment_plan.splice(index, 1);
}
function fillByTotal() {
  fillPlanAmounts(draft.value, total.value);
}
function save() {
  tried.value = true;
  if (errors.value.length) return;
  emit('save', supplierPayload(props.approval, draft.value));
}
</script>

<template>
  <div v-if="open && draft" class="pa-drawer-wrap" @keydown.esc="emit('close')">
    <div class="pa-drawer-mask" @click="emit('close')"></div>
    <aside ref="panel" class="pa-drawer" role="dialog" aria-modal="true" aria-label="编辑供应商报价">
      <header class="pa-drawer-head">
        <div>
          <div class="muted">{{ approval.name }} · {{ isExisting ? '编辑供应商报价' : '新增供应商' }}</div>
          <div class="pa-drawer-title">{{ draft.supplier || '新供应商' }}</div>
        </div>
        <button type="button" class="pa-x" aria-label="关闭" @click="emit('close')">×</button>
      </header>

      <div class="pa-drawer-body">
        <section>
          <div class="split"><h4>① 报价</h4><span class="muted">没有报价的物料留空 · 只有采购、草稿状态下才能改</span></div>
          <div class="f pa-name"><label for="pa-supplier-name">供应商名称 <b>*</b></label><input id="pa-supplier-name" v-model="draft.supplier" placeholder="供应商全称" /></div>
          <div class="pa-quote-grid pa-quote-head"><span>物料</span><span class="r">数量</span><span>单价（元）</span><span class="r">总价</span><span>货期</span></div>
          <div v-for="line in lines" :key="line.name" class="pa-quote-grid">
            <span><b>{{ line.item_name }}</b><span class="muted pa-block">{{ line.specification || '—' }}</span></span>
            <span class="r num">{{ quantity(line.quantity) }} {{ line.unit }}</span>
            <input v-model.number="draft.prices[line.name].unit_price" class="cell r" type="number" min="0.01" step="0.01" placeholder="单价" :aria-label="`${line.item_name} 单价`" />
            <span class="r num strong">{{ draftLineTotal(draft, line) === null ? '—' : money(draftLineTotal(draft, line)) }}</span>
            <input v-model="draft.prices[line.name].delivery_date" class="cell" type="date" :aria-label="`${line.item_name} 货期`" />
          </div>
          <div class="pa-quote-total"><span>报价合计</span><span class="num">{{ money(total) }}</span></div>
        </section>

        <section>
          <h4>② 商务条件</h4>
          <div class="form pa-terms-form">
            <div class="f s2"><label for="pa-pay-method">付款方式 <b>*</b></label><input id="pa-pay-method" v-model="draft.payment_method" placeholder="例如：预付 30%，验收后 70%" /></div>
            <div class="f"><label for="pa-currency">币种</label><input id="pa-currency" value="CNY（暂只支持人民币）" readonly /></div>
            <div class="f"><label for="pa-tax">税率 %</label><input id="pa-tax" v-model.number="draft.tax_rate" type="number" min="0" max="100" step="0.01" /></div>
            <div class="f s2"><label for="pa-entity">演示员工116主体</label><input id="pa-entity" v-model="draft.contract_entity" placeholder="我方签约主体" /></div>
          </div>
        </section>

        <section>
          <div class="split">
            <h4>③ 付款计划</h4>
            <span class="pa-plan-tools"><button type="button" class="link" @click="addRow">＋ 增加期次</button><button type="button" class="link" @click="fillByTotal">按报价总额</button></span>
          </div>
          <div v-for="(row, index) in draft.payment_plan" :key="index" class="pa-plan-card">
            <div class="pa-plan-row1">
              <div class="f"><label>期次</label><input v-model="row.installment_name" class="cell" placeholder="期次" /></div>
              <div class="f"><label>付款阶段</label><select v-model="row.payment_stage" class="cell"><option v-for="stage in PAYMENT_STAGES" :key="stage">{{ stage }}</option></select></div>
              <div class="f"><label>比例 %</label><input :value="row.percentage" class="cell r" type="number" min="0.01" max="100" step="0.01" @input="setPercentage(row, $event.target.value)" /></div>
              <div class="f"><label>金额</label><input v-model.number="row.amount" class="cell r" type="number" min="0.01" step="0.01" /></div>
            </div>
            <div class="pa-plan-row2">
              <div class="f"><label>计划付款日期</label><input v-model="row.planned_date" class="cell" type="date" /></div>
              <div class="f"><label>触发条件</label><input v-model="row.trigger_condition" class="cell" list="pa-trigger-list" placeholder="例如：演示员工116生效" /></div>
              <div class="f"><label>发票要求</label><select v-model="row.invoice_requirement" class="cell"><option v-for="item in INVOICE_REQUIREMENTS" :key="item">{{ item }}</option></select></div>
              <button type="button" class="pa-x sm" title="删除期次" :disabled="draft.payment_plan.length === 1" aria-label="删除期次" @click="removeRow(index)">×</button>
            </div>
          </div>
          <datalist id="pa-trigger-list"><option v-for="item in TRIGGER_SUGGESTIONS" :key="item" :value="item"></option></datalist>
          <div :class="planMatches ? 'ok' : 'err'">比例合计 {{ Number(totals.percentage.toFixed(4)) }}%，金额合计 {{ money(totals.amount) }}，{{ planMatches ? '与报价合计一致。' : `需要比例合计 100%、金额合计等于报价合计 ${money(total)}。` }}</div>
        </section>

        <section>
          <h4>④ 说明</h4>
          <div class="f"><textarea v-model="draft.note" rows="2" placeholder="交付能力、质量、商务说明" aria-label="报价说明"></textarea></div>
          <label class="pa-check-line"><input v-model="draft.is_recommended" type="checkbox" /> 采购推荐这家</label>
        </section>
      </div>

      <footer class="pa-drawer-foot">
        <div v-if="tried && errors.length" class="err" role="alert"><div v-for="item in errors" :key="item">{{ item }}</div></div>
        <div v-else-if="error" class="err" role="alert">{{ error }}</div>
        <div class="pa-foot-row">
          <template v-if="isExisting && askDelete">
            <span class="pa-confirm-text">删除 {{ draft.original_supplier }} 对整张单的报价？</span>
            <button type="button" class="btn sm danger" :disabled="busy" @click="emit('delete', draft.original_supplier)">确认删除</button>
            <button type="button" class="btn sm" @click="askDelete = false">返回</button>
          </template>
          <button v-else-if="isExisting" type="button" class="btn danger" @click="askDelete = true">删除这家供应商</button>
          <span class="pa-spacer"></span>
          <button type="button" class="btn" @click="emit('close')">取消</button>
          <button type="button" class="btn pri lg" :disabled="busy" @click="save">保存</button>
        </div>
      </footer>
    </aside>
  </div>
</template>
