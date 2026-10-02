<script setup>
// 线条图标，名字见 lib/rdIcons.js。
import { computed } from 'vue';
import { RD_ICONS } from '../../lib/rdIcons.js';

const props = defineProps({ name: { type: String, required: true } });
const paths = computed(() => RD_ICONS[props.name] || '');
</script>

<template>
  <svg class="ic" viewBox="0 0 24 24" aria-hidden="true" v-html="paths"></svg>
</template>
