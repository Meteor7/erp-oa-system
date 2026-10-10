<script setup>
// 审批进度：竖向时间轴，每一步有姓名、岗位、状态和时间，被驳回的步骤带意见。
defineProps({
  items: { type: Array, default: () => [] },
});
</script>

<template>
  <div class="af-tl">
    <div v-for="(item, index) in items" :key="item.key" :class="['s', item.cls]">
      <div class="rail"><i></i><span v-if="index < items.length - 1"></span></div>
      <div class="b"><b>{{ item.who }}</b> <span class="ac-note">{{ item.role }} · {{ item.sub }}</span><div v-if="item.note" class="ac-note">{{ item.note }}</div></div>
    </div>
    <div v-if="!items.length" class="ac-note">还没有提交审批</div>
  </div>
</template>
