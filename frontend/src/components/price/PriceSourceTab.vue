<script setup>
// "PR 待比价物料"：按 PR 分组列出还没被价格审批占满的物料，采购勾选并填本次比价数量，生成价格审批单。
import { computed, reactive, ref, watch } from 'vue';
import {
  availableLineCount, createApprovalLines, filterPrs, lineRemaining, occupiedQuantity, quantity,
  quantityError, selectedLines, selectionSummary, sourceKey, usageByPrLine, usageText,
} from '../../lib/priceView.js';

const props = defineProps({
  prs: { type: Array, default: () => [] },
  approvals: { type: Array, default: () => [] },
  pos: { type: Array, default: () => [] },
  canEdit: { type: Boolean, default: false },
  busy: { type: Boolean, default: false },
  focusPr: { type: String, default: '' },
  contextRequest: { type: String, default: '' },
});
const emit = defineEmits(['create', 'clear-focus']);

const search = ref('');
const availability = ref(props.focusPr ? 'all' : 'available');
const selected = ref(new Set());
const quantities = reactive({});
const filters = [
  { key: 'available', label: '可提价格审批' },
  { key: 'all', label: '全部 PR' },
  { key: 'exhausted', label: '已无可选物料' },
];

const rows = computed(() => filterPrs(props.prs, { query: search.value, availability: availability.value, focusPr: props.focusPr }));
const usage = computed(() => usageByPrLine(props.approvals, props.pos));
const pickedRows = computed(() => selectedLines(props.prs, selected.value, quantities));
const summary = computed(() => selectionSummary(pickedRows.value));
const selectableKeys = computed(() => rows.value.flatMap((pr) => (pr.lines || []).filter((line) => lineRemaining(line) > 0).map((line) => sourceKey(pr, line))));
const allPicked = computed(() => selectableKeys.value.length > 0 && selectableKeys.value.every((key) => selected.value.has(key)));

function usedBy(line) {
  return usageText(usage.value.get(line.name) || []);
}
function groupRequests(pr) {
  return [...new Set((pr.lines || []).map((line) => line.source_request).filter(Boolean))].join('、') || '—';
}
function groupProjects(pr) {
  return [...new Set((pr.lines || []).map((line) => line.project).filter(Boolean))].join('、');
}
function toggle(pr, line, checked) {
  const key = sourceKey(pr, line);
  const next = new Set(selected.value);
  if (checked) {
    next.add(key);
    if (!quantities[key]) quantities[key] = lineRemaining(line);
  } else next.delete(key);
  selected.value = next;
}
function toggleAll(checked) {
  const next = new Set(selected.value);
  rows.value.forEach((pr) => (pr.lines || []).forEach((line) => {
    if (lineRemaining(line) <= 0) return;
    const key = sourceKey(pr, line);
    if (checked) {
      next.add(key);
      if (!quantities[key]) quantities[key] = lineRemaining(line);
    } else next.delete(key);
  }));
  selected.value = next;
}
function rowError(pr, line) {
  const key = sourceKey(pr, line);
  return selected.value.has(key) ? quantityError(line, quantities[key]) : '';
}
function create() {
  if (!pickedRows.value.length || summary.value.invalid) return;
  emit('create', createApprovalLines(pickedRows.value));
}

// 数据刷新后（生成了价格审批单），去掉已经没有可选数量的勾选。
watch(() => props.prs, () => {
  const alive = new Set();
  props.prs.forEach((pr) => (pr.lines || []).forEach((line) => { if (lineRemaining(line) > 0) alive.add(sourceKey(pr, line)); }));
  selected.value = new Set([...selected.value].filter((key) => alive.has(key)));
});
</script>

<template>
  <div class="pa-source">
    <div v-if="!canEdit" class="banner pa-readonly" role="status">你在这里只能查看。发起价格审批是采购的工作；PR 由 PMC 在物料进度看板提出。</div>
    <div v-if="focusPr" class="banner pa-focus" role="status">
      通知链接：只看 {{ focusPr }}。
      <button type="button" class="link" @click="emit('clear-focus')">看全部 PR</button>
    </div>

    <div class="filter-bar">
      <input v-model="search" type="search" placeholder="搜索 PR、OA、项目或物料" aria-label="搜索 PR、OA、项目或物料" />
      <div class="seg" role="group" aria-label="PR 可用状态筛选">
        <button v-for="item in filters" :key="item.key" type="button" :aria-pressed="availability === item.key" @click="availability = item.key">{{ item.label }}</button>
      </div>
    </div>

    <section class="panel flush">
      <div class="tbl">
        <table class="pa-src">
          <thead>
            <tr>
              <th class="pa-check"><input type="checkbox" :checked="allPicked" :disabled="!canEdit || !selectableKeys.length" aria-label="选择当前列表里所有可选物料" @change="toggleAll($event.target.checked)" /></th>
              <th>物料编号 / 流水号</th><th>来源 OA / 项目</th><th>物料名称</th><th>规格型号</th>
              <th class="r">PR 数量</th><th class="r">已被占用</th><th class="r">可选</th><th class="r pa-take">本次比价数量</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="pr in rows" :key="pr.name">
              <tr class="pa-pr-row">
                <td colspan="9">
                  <div class="pa-pr-head">
                    <b class="num">{{ pr.name }}</b>
                    <span class="muted">单据状态 {{ pr.status || '待采购' }}</span>
                    <span :class="['pill', availableLineCount(pr) ? 'p-jade' : 'p-gray']">{{ availableLineCount(pr) ? `可提价格审批 ${availableLineCount(pr)} 项` : '已无可选物料' }}</span>
                    <span class="muted pa-pr-meta">{{ pr.lines.length }} 项物料 · 来源 {{ groupRequests(pr) }}<template v-if="groupProjects(pr)"> · {{ groupProjects(pr) }}</template></span>
                  </div>
                </td>
              </tr>
              <tr v-for="line in pr.lines" :key="line.name" :class="{ 'pa-dim': lineRemaining(line) <= 0, on: selected.has(`${pr.name}:${line.name}`) }">
                <td class="pa-check">
                  <input type="checkbox" :disabled="!canEdit || lineRemaining(line) <= 0" :checked="selected.has(`${pr.name}:${line.name}`)" :aria-label="`选择 ${line.item_name}`" @change="toggle(pr, line, $event.target.checked)" />
                </td>
                <td><div class="num">{{ line.material_code || '—' }}</div><div class="muted num">{{ line.material_serial }}</div></td>
                <td><div>{{ line.source_request || '—' }}</div><div class="muted">{{ line.project || '—' }}</div></td>
                <td><b>{{ line.item_name }}</b></td>
                <td>{{ line.specification || '—' }}</td>
                <td class="r num">{{ quantity(line.quantity) }} {{ line.unit }}</td>
                <td class="r" :title="usedBy(line) || undefined">
                  <div class="num">{{ quantity(occupiedQuantity(line)) }} {{ line.unit }}</div>
                  <div v-if="usedBy(line)" class="muted pa-usedby">{{ usedBy(line) }}</div>
                </td>
                <td class="r num pa-free">{{ quantity(lineRemaining(line)) }} {{ line.unit }}</td>
                <td class="r">
                  <input v-model.number="quantities[`${pr.name}:${line.name}`]" class="cell r" type="number" min="0.0001" :max="lineRemaining(line)" step="0.0001"
                    :disabled="!canEdit || !selected.has(`${pr.name}:${line.name}`)" :aria-label="`本次比价数量 ${line.material_serial}`" />
                  <div v-if="rowError(pr, line)" class="err">{{ rowError(pr, line) }}</div>
                </td>
              </tr>
            </template>
            <tr v-if="!rows.length">
              <td colspan="9" class="empty">{{ contextRequest ? `${contextRequest} 当前没有可询价的 PR 物料；请先确认 PMC 已生成 PR，或查看该 OA 的价格审批单。` : '当前没有符合条件的 PR 物料' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <div v-if="canEdit && summary.count" class="batch-bar">
      <span>已选 <b>{{ summary.count }}</b> 项物料 · 来自 {{ summary.prs }} 张 PR、{{ summary.requests }} 张 OA</span>
      <span class="muted pa-batch-hint">可以跨 PR、跨 OA、跨项目合并成一张；生成后进入"价格审批单"，录入各家报价</span>
      <button type="button" class="btn pri lg pa-push" :disabled="busy || summary.invalid > 0" @click="create">生成价格审批单</button>
    </div>
    <div v-if="summary.invalid" class="err">有 {{ summary.invalid }} 项的比价数量不合法（要大于 0，且不超过可选数量）。</div>

    <p class="muted foot">"已被占用"= PR 数量 − 可选数量，包括已进价格审批单（草稿 / 待审批占着，撤回或取消才释放）和已生成 PO 的数量，鼠标放上去显示是哪一张。</p>
  </div>
</template>
