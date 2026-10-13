<script setup>
// 2026-10-13 排版：本期没有数据的块不占卡片，收成一行“暂无数据：标题（副标题）· …”，放在页签 / 分段的最后；
// 标题有跳转的照样能点（比如“本月宿舍费用”点进去去登记）。
import { computed } from 'vue';
import { emptyStripItems } from '../../lib/dashboardLayout.js';
import { targetHint } from '../../lib/dashboardTargets.js';

const props = defineProps({
  blocks: { type: Array, default: () => [] },
  resolve: { type: Function, required: true },
});
const emit = defineEmits(['go']);
const items = computed(() => emptyStripItems(props.blocks).map((item) => ({ ...item, link: props.resolve(item.target) })));
</script>

<template>
  <p v-if="items.length" class="db-nodata" role="note">
    <span class="db-nodata-h">暂无数据：</span>
    <template v-for="(item, index) in items" :key="item.key || index">
      <span v-if="index" class="db-nodata-sep" aria-hidden="true">·</span>
      <span class="db-nodata-i" :data-block="item.key">
        <button v-if="item.link.state === 'link'" type="button" class="db-link" @click="emit('go', item.link.to)">{{ item.title }}</button>
        <span v-else :title="targetHint(item.link.state) || undefined">{{ item.title }}</span>
        <span v-if="item.sub" class="db-mut">（{{ item.sub }}）</span>
      </span>
    </template>
  </p>
</template>
