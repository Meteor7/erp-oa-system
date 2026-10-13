<script setup>
// 价格审批单列表：按状态筛选、搜索，点一行进入详情。看板点进来带 ?status=pending（待审批）就是筛好的。
import { computed, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { APPROVAL_FILTERS, amountText, approvalTone, filterApprovals, pillClass, splitList } from '../../lib/priceView.js';

const props = defineProps({
  approvals: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
});
const emit = defineEmits(['open']);

const route = useRoute();
const presetFilter = (query) => (APPROVAL_FILTERS.some((item) => item.key === query.status) ? String(query.status) : 'all');
const filter = ref(presetFilter(route.query));
watch(() => route.query.status, () => { filter.value = presetFilter(route.query); });
const search = ref('');
const rows = computed(() => filterApprovals(props.approvals, filter.value, search.value));

function countOf(key) {
  return filterApprovals(props.approvals, key, '').length;
}
function sourceText(item) {
  const requests = splitList(item.source_requests);
  return requests.length ? requests.join('、') : '—';
}
function totalText(item) {
  return (item.lines || []).some((line) => line.selected_supplier) ? amountText(item.total_amount, item.amounts_hidden) : '—';
}
</script>

<template>
  <div class="pa-approvals">
    <div class="filter-bar">
      <input v-model="search" type="search" placeholder="搜索价格审批单、PR、OA、项目或供应商" aria-label="搜索价格审批单" />
      <div class="seg" role="group" aria-label="价格审批单状态筛选">
        <button v-for="item in APPROVAL_FILTERS" :key="item.key" type="button" :aria-pressed="filter === item.key" @click="filter = item.key">{{ item.label }} {{ countOf(item.key) }}</button>
      </div>
    </div>
    <section class="panel flush">
      <div class="tbl">
        <table>
          <thead>
            <tr><th>价格审批单</th><th>状态</th><th>来源 PR</th><th>来源 OA / 项目</th><th class="r">物料</th><th class="r">供应商</th><th class="r">成交总额</th><th></th></tr>
          </thead>
          <tbody>
            <tr v-for="item in rows" :key="item.name" class="row-sel" tabindex="0" @click="emit('open', item.name)" @keydown.enter="emit('open', item.name)">
              <td><b class="num">{{ item.name }}</b></td>
              <td>
                <span :class="pillClass(approvalTone(item.status))">{{ item.status }}</span>
                <span v-if="item.can_select_quote && item.status === '待审批'" class="pill p-brand pa-mine">待我审批</span>
              </td>
              <td>{{ item.source_prs || '—' }}</td>
              <td><div>{{ sourceText(item) }}</div><div class="muted">{{ splitList(item.source_projects).join('、') || '—' }}</div></td>
              <td class="r">{{ (item.lines || []).length }} 项</td>
              <td class="r">{{ (item.supplier_comparisons || []).length }} 家</td>
              <td class="r num">{{ totalText(item) }}</td>
              <td class="r"><button type="button" class="link" @click.stop="emit('open', item.name)">查看 →</button></td>
            </tr>
            <tr v-if="!rows.length"><td colspan="8" class="empty">{{ loading ? '正在加载…' : (approvals.length ? '没有符合条件的价格审批单' : '暂无价格审批单') }}</td></tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>
