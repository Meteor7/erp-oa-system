<script setup>
// 到货与验收：整张 PO 共用。生产主管有四种登记：到货 / 验收 / 换货到货 / 退货发出（记录只增不改）；其他人只读。
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue';
import { createResource } from 'frappe-ui';
import {
  INSPECT_CHOICES, MODE_CONFIG, MODE_ORDER, REFUND_NOTICE, buildFulfilmentRequest, defaultQuantity, eligibleLines,
  fulfilmentModes, fulfilmentRoleNote, lineHint, lineState, money, pickMode, quantity, roleHint, sortRecordsDesc,
  todayString, validateFulfilment,
} from '../../lib/paymentView.js';
import { PROCUREMENT_API, errorText, uploadEvidence } from './paymentApi.js';
import PayRecordList from './PayRecordList.vue';

const props = defineProps({
  group: { type: Object, required: true },
  canFulfil: { type: Boolean, default: false },
  canPurchase: { type: Boolean, default: false },
});
const emit = defineEmits(['changed']);

// 四种登记各一个接口（都只有生产主管 / 系统管理员能调用，服务端再校验一次）。
const resources = {
  record_po_receipt: createResource({ url: PROCUREMENT_API + 'record_po_receipt', method: 'POST' }),
  record_po_inspection: createResource({ url: PROCUREMENT_API + 'record_po_inspection', method: 'POST' }),
  record_po_exchange_receipt: createResource({ url: PROCUREMENT_API + 'record_po_exchange_receipt', method: 'POST' }),
  record_po_return: createResource({ url: PROCUREMENT_API + 'record_po_return', method: 'POST' }),
};

const modes = computed(() => fulfilmentModes(props.group, { canFulfil: props.canFulfil }));
const mode = ref('');
watch(modes, (list) => { mode.value = pickMode(list, mode.value); }, { immediate: true });
const config = computed(() => MODE_CONFIG[mode.value] || null);
const eligible = computed(() => new Set(eligibleLines(mode.value, props.group.lines).map((line) => line.name)));
const records = computed(() => sortRecordsDesc(props.group.records || []));
const note = computed(() => fulfilmentRoleNote({
  canFulfil: props.canFulfil, canPurchase: props.canPurchase, modeCount: modes.value.length, poStatus: props.group.po_status,
}));
const hint = computed(() => roleHint({ canFulfil: props.canFulfil, canPurchase: props.canPurchase }));
const hasReturning = computed(() => props.group.summary.hasReturn);

const drafts = reactive({ arrive: {}, inspect: {}, exchange: {}, return: {} });
const dates = reactive(Object.fromEntries(MODE_ORDER.map((key) => [key, todayString()])));
const files = reactive(Object.fromEntries(MODE_ORDER.map((key) => [key, null])));
const notes = reactive(Object.fromEntries(MODE_ORDER.map((key) => [key, ''])));
const busy = ref(false);
const uploading = ref(false);
const error = ref('');
const ok = ref('');
let okTimer = null;
onBeforeUnmount(() => clearTimeout(okTimer));

function resetModeState(key) {
  drafts[key] = {};
  files[key] = null;
  notes[key] = '';
  dates[key] = todayString();
}
watch(() => props.group.po, () => {
  MODE_ORDER.forEach(resetModeState);
  error.value = '';
  ok.value = '';
});
watch(mode, () => { error.value = ''; });
// 提示只在"自己点了别的登记类型"时清掉：登记完成后页面会自动切到下一个类型，那时提示还要留着。
function selectMode(key) { mode.value = key; ok.value = ''; }

function qtyValue(line) {
  const raw = drafts[mode.value][line.name];
  return raw === undefined ? defaultQuantity(mode.value, line) : raw;
}
function setQty(line, value) { drafts[mode.value][line.name] = value; }
function resultOf(line) { return drafts.inspect[line.name]?.result || ''; }
function reasonOf(line) { return drafts.inspect[line.name]?.reason || ''; }
function setResult(line, value) { drafts.inspect[line.name] = { ...(drafts.inspect[line.name] || {}), result: value }; }
function setReason(line, value) { drafts.inspect[line.name] = { ...(drafts.inspect[line.name] || {}), reason: value }; }

async function onFile(event) {
  const file = event.target.files?.[0];
  event.target.value = '';
  if (!file) return;
  uploading.value = true;
  error.value = '';
  try { files[mode.value] = await uploadEvidence(file); } catch (err) { error.value = errorText(err, '资料上传失败'); } finally { uploading.value = false; }
}

async function submit() {
  if (busy.value || !mode.value) return;
  error.value = '';
  ok.value = '';
  const key = mode.value;
  const meta = { date: dates[key], fileRef: files[key]?.name || '', note: notes[key] };
  const check = validateFulfilment(key, props.group, drafts[key], meta);
  if (check.error) { error.value = check.error; return; }
  const request = buildFulfilmentRequest(key, props.group.po, check.lines, meta);
  busy.value = true;
  try {
    await resources[request.method].submit(request.params);
    ok.value = MODE_CONFIG[key].done;
    clearTimeout(okTimer);
    okTimer = setTimeout(() => { ok.value = ''; }, 8000);
    resetModeState(key);
    emit('changed');
  } catch (err) { error.value = errorText(err, `${MODE_CONFIG[key].label}失败`); } finally { busy.value = false; }
}
</script>

<template>
  <section class="panel pay-fulfil">
    <div class="pt">
      <span>到货与验收 <span class="muted">整张 PO 共用；下面所有付款期次都按这里的结果判断</span></span>
      <span class="muted">{{ hint }}</span>
    </div>

    <div v-if="modes.length" class="pay-modes" role="tablist" aria-label="登记类型">
      <button v-for="item in modes" :key="item.key" type="button" role="tab" :aria-selected="mode === item.key" :class="{ on: mode === item.key }" @click="selectMode(item.key)">{{ item.label }}</button>
    </div>

    <div class="tbl">
      <table class="pay-lines">
        <thead>
          <tr>
            <th>物料</th><th class="r">订购</th><th class="r">已到</th><th class="r">未到</th>
            <th v-if="config">{{ config.column }}</th><th>验收结果</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="line in group.lines" :key="line.name">
            <td>
              <b>{{ line.item_name }}</b>
              <div class="muted">{{ [line.material_serial, line.material_code, line.specification].filter(Boolean).join(' · ') }} · {{ money(line.unit_price, group.currency) }} / {{ line.unit }}</div>
              <div v-if="line.source_request || line.source_pr" class="muted">来源 {{ [line.source_request, line.source_pr].filter(Boolean).join(' / ') }}</div>
            </td>
            <td class="r num">{{ quantity(line.quantity) }} {{ line.unit }}</td>
            <td class="r num">{{ quantity(line.received_quantity) }} {{ line.unit }}</td>
            <td class="r num" :class="lineState(line).left > 0 ? 'pay-left' : 'pay-full'">{{ lineState(line).left > 0 ? `${quantity(lineState(line).left)} ${line.unit}` : '已到齐' }}</td>
            <td v-if="config">
              <template v-if="eligible.has(line.name) && mode === 'inspect'">
                <select class="cell" :value="resultOf(line)" :aria-label="`${line.item_name} 验收结果`" @change="setResult(line, $event.target.value)">
                  <option value="">不变</option>
                  <option v-for="choice in INSPECT_CHOICES" :key="choice.value" :value="choice.value">{{ choice.label }}</option>
                </select>
                <input v-if="resultOf(line) && resultOf(line) !== '已通过'" class="cell pay-reason" :value="reasonOf(line)" placeholder="原因（必填）" :aria-label="`${line.item_name} 换货或退货原因`" @input="setReason(line, $event.target.value)" />
              </template>
              <template v-else-if="eligible.has(line.name)">
                <input class="cell pay-qty" type="number" min="0" step="any" :value="qtyValue(line)" :aria-label="`${line.item_name} ${config.column}`" @input="setQty(line, $event.target.value)" />
                <span class="muted"> {{ line.unit }}</span>
                <div v-if="mode === 'arrive'" class="muted">一次到齐，不分批</div>
              </template>
              <span v-else class="muted">—</span>
            </td>
            <td>
              <span class="pill" :class="`p-${lineState(line).tone}`">{{ lineState(line).label }}</span>
              <div v-if="lineHint(line, records, canFulfil)" class="muted pay-reason-text">{{ lineHint(line, records, canFulfil) }}</div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="modes.length && config" class="pay-form">
      <div class="f">
        <label :for="`pay-date-${mode}`">{{ config.dateLabel }}<b>*</b></label>
        <input :id="`pay-date-${mode}`" v-model="dates[mode]" type="date" />
      </div>
      <div class="f">
        <label>{{ config.fileLabel }}<b>*</b>（一份文件）</label>
        <label class="pay-file">
          <span>{{ files[mode]?.filename || '＋ 选择文件（pdf / 图片 / Office）' }}</span>
          <input type="file" accept=".pdf,.png,.jpg,.jpeg,.doc,.docx,.xls,.xlsx" :disabled="uploading || busy" @change="onFile" />
        </label>
      </div>
      <div class="f">
        <label :for="`pay-note-${mode}`">备注（可选）</label>
        <input :id="`pay-note-${mode}`" v-model="notes[mode]" type="text" placeholder="可不填" />
      </div>
      <button type="button" class="btn dark" :disabled="busy || uploading" @click="submit">{{ busy ? '提交中…' : config.submit }}</button>
    </div>
    <p v-if="modes.length && config" class="pay-warn muted">{{ config.warn }}</p>
    <p v-else-if="note" class="pay-warn muted">{{ note }}</p>
    <div v-if="ok" class="banner ok" role="status">{{ ok }}</div>
    <div v-if="error" class="banner err" role="alert">{{ error }}</div>
    <p v-if="hasReturning && mode !== 'return'" class="pay-warn muted">{{ REFUND_NOTICE }}。</p>

    <h4>到货、验收、换货、退货记录（只增不改，共 {{ records.length }} 条）</h4>
    <PayRecordList :records="records" />
  </section>
</template>
