<script setup>
// 研发台账页面的外框：页头（标题、说明、右侧控件）+ 内容。样式见 styles/rdUi.css。
import '../../styles/rdUi.css';

defineProps({
  title: { type: String, required: true },
  subtitle: { type: String, default: '' },
  crumb: { type: String, default: '研发台账' },
});
</script>

<template>
  <div class="rd">
    <header class="top">
      <div>
        <div class="crumb">{{ crumb }}</div>
        <h1>{{ title }}</h1>
        <p v-if="subtitle">{{ subtitle }}</p>
      </div>
      <div class="ctl"><slot name="ctl" /></div>
    </header>
    <slot />
  </div>
</template>
