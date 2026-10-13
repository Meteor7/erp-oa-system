<script setup>
// 「需要关注」：每条点一下带着筛选打开对应页面。
// 2026-10-13 排版：先列 5 条，“全部 N 条”就地展开（不跳页）。
import { computed, ref, watch } from 'vue';
import { EMPTY_ALERT_TEXT } from '../../lib/dashboardView.js';
import { limitRows } from '../../lib/dashboardLayout.js';
import { targetHint } from '../../lib/dashboardTargets.js';

const props = defineProps({
  alerts: { type: Array, default: () => [] },
  resolve: { type: Function, required: true },
});
const emit = defineEmits(['go']);
const open = ref(false);
// 换了一批（换页签、换月份）就收起来，不沿用上一批的展开状态
watch(() => props.alerts, () => { open.value = false; });
const view = computed(() => limitRows(props.alerts, open.value));
</script>

<template>
  <section class="db-card db-alerts" aria-labelledby="db-alerts-h">
    <div class="db-hd">
      <h2 id="db-alerts-h">需要关注</h2>
      <span v-if="alerts.length" class="db-cnt">{{ alerts.length }}</span>
      <span class="db-mut">点一条，直接带着筛选打开对应页面</span>
    </div>
    <p v-if="!alerts.length" class="db-empty">{{ EMPTY_ALERT_TEXT }}</p>
    <ul v-else class="db-rows">
      <li v-for="item in view.shown" :key="item.key" class="db-li">
        <component :is="resolve(item.target).state === 'link' ? 'button' : 'div'" class="db-row" :data-alert="item.key"
          :class="{ 'is-link': resolve(item.target).state === 'link', 'is-off': ['denied', 'unknown'].includes(resolve(item.target).state) }"
          :type="resolve(item.target).state === 'link' ? 'button' : undefined"
          :title="targetHint(resolve(item.target).state) || undefined"
          @click="resolve(item.target).state === 'link' && emit('go', resolve(item.target).to)">
          <span class="db-row-main">
            <span class="db-row-t"><span class="db-tag" :class="item.toneClass">{{ item.toneLabel }}</span> {{ item.title }}</span>
            <span v-if="item.sub" class="db-mut">{{ item.sub }}</span>
          </span>
          <span v-if="item.go && resolve(item.target).state === 'link'" class="db-go">{{ item.go }} →</span>
        </component>
      </li>
    </ul>
    <div v-if="view.more" class="db-foot">
      <button type="button" class="db-link" :aria-expanded="open ? 'true' : 'false'" @click="open = !open">{{ open ? '收起' : `全部 ${view.total} 条` }}</button>
    </div>
  </section>
</template>
