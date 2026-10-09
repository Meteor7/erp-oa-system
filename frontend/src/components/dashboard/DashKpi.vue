<script setup>
// 指标卡：能跳转的是按钮；后端没给跳转的只是显示；有跳转但当前账号打不开 / 目标未知的置灰。
import { computed } from 'vue';
import { targetHint } from '../../lib/dashboardTargets.js';

const props = defineProps({
  kpi: { type: Object, required: true },
  state: { type: Object, default: () => ({ state: 'none', to: null }) },
});
const emit = defineEmits(['go']);

const clickable = computed(() => props.state.state === 'link');
const off = computed(() => props.state.state === 'denied' || props.state.state === 'unknown');
const offHint = computed(() => targetHint(props.state.state));
</script>

<template>
  <component :is="clickable ? 'button' : 'div'" class="db-kpi" :class="[kpi.toneClass, { 'is-link': clickable, 'is-off': off }]"
    :type="clickable ? 'button' : undefined" :title="off ? offHint : undefined" :aria-disabled="off ? 'true' : undefined"
    :data-kpi="kpi.key" @click="clickable && emit('go', state.to)">
    <span class="db-kpi-l">
      <span class="db-kpi-name">{{ kpi.label }}</span>
      <span v-if="kpi.preview" class="db-pill" title="含未定版月份的预览数字">预览</span>
      <span v-if="kpi.hint" class="db-q" role="img" :aria-label="kpi.hint" :title="kpi.hint">?</span>
    </span>
    <span class="db-kpi-v">{{ kpi.value }}<small v-if="kpi.unit">{{ kpi.unit }}</small></span>
    <span v-if="kpi.sub" class="db-kpi-s">{{ kpi.sub }}</span>
  </component>
</template>
