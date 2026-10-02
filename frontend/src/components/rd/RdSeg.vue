<script setup>
// 黑底白字的分段切换（月度 / 年度、汇总 / 资本化 / 费用化 等）。options: [{ value, label }]
defineProps({
  modelValue: { type: String, required: true },
  options: { type: Array, required: true },
  label: { type: String, default: '' },
});
const emit = defineEmits(['update:modelValue']);
</script>

<template>
  <div class="seg" role="group" :aria-label="label || undefined">
    <button v-for="item in options" :key="item.value" type="button" :aria-pressed="modelValue === item.value" @click="emit('update:modelValue', item.value)">{{ item.label }}</button>
  </div>
</template>
