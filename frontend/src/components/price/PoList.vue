<script setup>
// PO 列表：按合同办理 / 执行 / 关闭筛选，点一行进入 PO 与合同详情。
import { computed, ref } from 'vue';
import { PO_FILTERS, filterPos, money, pillClass, poNextStep, poSources, poTone, splitList } from '../../lib/priceView.js';

const props = defineProps({
  pos: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
});
const emit = defineEmits(['open']);

const filter = ref('all');
const search = ref('');
const rows = computed(() => filterPos(props.pos, filter.value, search.value));
const countOf = (key) => filterPos(props.pos, key, '').length;
const sourceText = (po) => poSources(po).requests.join('、') || '—';
const projectText = (po) => poSources(po).projects.join('、') || '—';
</script>

<template>
  <div class="pa-pos">
    <div class="filter-bar">
      <input v-model="search" type="search" placeholder="搜索 PO、供应商、价格审批单、OA 或项目" aria-label="搜索 PO" />
      <div class="seg" role="group" aria-label="PO 状态筛选">
        <button v-for="item in PO_FILTERS" :key="item.key" type="button" :aria-pressed="filter === item.key" @click="filter = item.key">{{ item.label }} {{ countOf(item.key) }}</button>
      </div>
    </div>
    <section class="panel flush">
      <div class="tbl">
        <table>
          <thead>
            <tr><th>PO</th><th>供应商</th><th>状态</th><th>下一步</th><th>来源价格审批 / OA</th><th class="r">物料</th><th class="r">PO 总额</th><th></th></tr>
          </thead>
          <tbody>
            <tr v-for="po in rows" :key="po.name" class="row-sel" tabindex="0" @click="emit('open', po.name)" @keydown.enter="emit('open', po.name)">
              <td><b class="num">{{ po.name }}</b></td>
              <td>{{ po.supplier }}</td>
              <td><span :class="pillClass(poTone(po.status))">{{ po.status }}</span></td>
              <td>{{ poNextStep(po) }}</td>
              <td><div>{{ splitList(po.source_price_approvals).join('、') || '—' }}</div><div class="muted">{{ sourceText(po) }} · {{ projectText(po) }}</div></td>
              <td class="r">{{ (po.lines || []).length }} 项</td>
              <td class="r num">{{ money(po.total_amount) }}</td>
              <td class="r"><button type="button" class="link" @click.stop="emit('open', po.name)">查看 →</button></td>
            </tr>
            <tr v-if="!rows.length"><td colspan="8" class="empty">{{ loading ? '正在加载…' : (pos.length ? '没有符合条件的 PO' : '暂无 PO') }}</td></tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>
