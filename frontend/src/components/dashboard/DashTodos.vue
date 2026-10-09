<script setup>
// 「要我处理」：等待最久的排在前面（后端已排好序）；没有待办写"没有需要你处理的事"。
import { EMPTY_TODO_TEXT } from '../../lib/dashboardView.js';
import { targetHint } from '../../lib/dashboardTargets.js';

defineProps({
  todos: { type: Array, default: () => [] },
  resolve: { type: Function, required: true },
});
const emit = defineEmits(['go']);
</script>

<template>
  <section class="db-card db-todos" aria-labelledby="db-todos-h">
    <div class="db-hd">
      <h2 id="db-todos-h">要我处理</h2>
      <span v-if="todos.length" class="db-cnt">{{ todos.length }}</span>
      <span class="db-mut">审批和需要我动手的事，等得最久的排在前面</span>
    </div>
    <p v-if="!todos.length" class="db-empty">{{ EMPTY_TODO_TEXT }}</p>
    <ul v-else class="db-rows">
      <li v-for="(item, index) in todos" :key="index" class="db-row" :class="{ 'is-link': resolve(item.target).state === 'link' }"
          @click="resolve(item.target).state === 'link' && emit('go', resolve(item.target).to)">
        <div class="db-row-main">
          <div class="db-row-t"><span class="db-tag" :class="item.toneClass">{{ item.kind }}</span> {{ item.title }}</div>
          <div v-if="item.sub" class="db-mut">{{ item.sub }}</div>
        </div>
        <button v-if="resolve(item.target).state === 'link'" type="button" class="db-btn is-pri" @click.stop="emit('go', resolve(item.target).to)">{{ item.btn }}</button>
        <button v-else-if="resolve(item.target).state !== 'none'" type="button" class="db-btn" disabled :title="targetHint(resolve(item.target).state)">{{ item.btn }}</button>
      </li>
    </ul>
  </section>
</template>
