<script setup>
import { useRoute } from 'vue-router';
import { canSee } from '../lib/access.js';

// 宿舍三个页面之间切换。名字和侧栏、页面标题保持一致（宿舍看板 / 宿舍基本信息管理 / 当月费用管理），
// 原来的标签是另一套叫法，和侧栏对不上。
const route = useRoute();
const tabs = [
  { to: '/accommodation', label: '宿舍看板' },
  { to: '/accommodation/master', label: '宿舍基本信息管理' },
  { to: '/accommodation/monthly', label: '当月费用管理' },
].filter((tab) => canSee(tab.to));   // 总经理、演示员工113经理打不开当月费用管理，就不显示这个标签
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
