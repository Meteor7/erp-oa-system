<script setup>
// 付款条件格：满足（绿）/ 未满足（黄）/ 本期不要求（灰）。
defineProps({ tiles: { type: Array, default: () => [] } });
</script>

<template>
  <div class="pay-gates">
    <div v-for="tile in tiles" :key="tile.key" class="pay-gate" :class="tile.state === 1 ? 'ok' : tile.state === 0 ? 'wait' : 'na'">
      <span>{{ tile.k }}</span>
      <b>{{ tile.v }}</b>
    </div>
  </div>
</template>
