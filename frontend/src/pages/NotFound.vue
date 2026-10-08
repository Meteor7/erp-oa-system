<script setup>
// 地址不对（拼错了、页面改过名、收藏的老链接）：说清楚是哪个地址，给一个回首页的入口。
import { computed } from 'vue';
import { useRoute } from 'vue-router';
import { firstVisiblePath } from '../lib/access';

const route = useRoute();
const wanted = computed(() => route.fullPath);
const home = computed(() => firstVisiblePath());
</script>

<template>
  <div class="flex flex-col items-center justify-center py-24 text-center" data-testid="not-found">
    <div class="mb-3 text-3xl">404</div>
    <div class="font-medium text-gray-700">页面不存在</div>
    <div class="mt-1 max-w-md break-all text-sm text-gray-400">找不到「{{ wanted }}」。地址可能写错了，或者这个页面已经改了位置。</div>
    <router-link :to="home" class="mt-5 rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-[#FF8F00]">回到首页</router-link>
  </div>
</template>
