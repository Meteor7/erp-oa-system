<script setup>
import { useRoute } from 'vue-router';

// 宿舍三个页面之间切换（看板 / 房间管理 / 当月费用登记）。
const route = useRoute();
const tabs = [
  { to: '/accommodation', label: '看板' },
  { to: '/accommodation/master', label: '房间管理' },
  { to: '/accommodation/monthly', label: '当月费用登记' },
];
</script>

<template>
  <nav aria-label="宿舍页面" class="inline-flex w-fit gap-1 rounded-[10px] border border-[#E3E6EC] bg-white p-1">
    <router-link
      v-for="tab in tabs" :key="tab.to" :to="tab.to"
      class="rounded-md px-3 py-1.5 text-sm no-underline md:px-4 md:py-2"
      :class="route.path === tab.to ? 'bg-[#1A2130] text-white' : 'text-[#3D4555] hover:bg-gray-100'"
      :aria-current="route.path === tab.to ? 'page' : undefined"
    >{{ tab.label }}</router-link>
  </nav>
</template>
